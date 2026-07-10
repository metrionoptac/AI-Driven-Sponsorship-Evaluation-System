"""
Folder Watcher — Monitors directories for new scanned documents.

Use case: Mail room scans physical letters → saves to a shared network folder.
This watcher detects new files and ingests them automatically.

Uses watchdog library for filesystem events (inotify on Linux,
ReadDirectoryChanges on Windows). Falls back to periodic directory scanning.
"""

import asyncio
import logging
import shutil
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from app.config import IntakeConfig
from app.intake.service import UnifiedIngestionService

logger = logging.getLogger(__name__)

# Wait after file creation before processing (ensure write is complete)
SETTLE_DELAY_SEC = 2

# File extensions we accept
ACCEPTED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".docx", ".doc", ".eml", ".msg",
}


class _FileHandler(FileSystemEventHandler):
    """Watchdog event handler — queues new files for async processing."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.suffix.lower() in ACCEPTED_EXTENSIONS:
            logger.info("New file detected: %s", file_path)
            # Schedule async processing from sync watchdog thread
            self.loop.call_soon_threadsafe(
                self.queue.put_nowait, str(file_path)
            )


class FolderWatcher:
    """
    Watches configured directories for new files (scanned documents).

    After processing, files are moved to a "processed" subdirectory
    to prevent re-processing.

    Usage:
        watcher = FolderWatcher(config, ingestion_service)
        asyncio.create_task(watcher.start())  # runs forever in background
    """

    def __init__(self, config: IntakeConfig, ingestion_service: UnifiedIngestionService):
        self.config = config
        self.ingestion = ingestion_service
        self._running = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._observer: Observer | None = None

    async def start(self):
        """Start watching all configured directories."""
        if not self.config.watch_folders:
            logger.info("No watch folders configured, folder watcher disabled")
            return

        self._running = True
        loop = asyncio.get_event_loop()

        # Set up watchdog observer (runs in its own thread)
        self._observer = Observer()
        handler = _FileHandler(self._queue, loop)

        for folder in self.config.watch_folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
                logger.info("Created watch directory: %s", folder_path)

            self._observer.schedule(handler, str(folder_path), recursive=False)
            logger.info("Watching directory: %s", folder_path)

        self._observer.start()

        # Recover claims orphaned by a crash mid-processing (B20): a
        # '<name>.processing' file with no live processing task gets renamed
        # back so the startup sweep below picks it up again.
        for folder in self.config.watch_folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                continue
            for orphan in folder_path.glob("*.processing"):
                original = orphan.with_name(orphan.name[: -len(".processing")])
                if not original.exists():
                    try:
                        orphan.rename(original)
                        logger.info("Recovered orphaned claim: %s", original.name)
                    except OSError:
                        pass

        # Process any existing files on startup
        await self._process_existing_files()

        # Process queue forever
        try:
            while self._running:
                try:
                    file_path = await asyncio.wait_for(
                        self._queue.get(), timeout=self.config.folder_poll_interval_sec
                    )
                    await self._process_file(file_path)
                except asyncio.TimeoutError:
                    # Periodic check for files that watchdog might have missed
                    await self._process_existing_files()
                except asyncio.CancelledError:
                    break
        finally:
            self._observer.stop()
            self._observer.join()

    async def stop(self):
        """Gracefully stop the watcher."""
        self._running = False
        if self._observer:
            self._observer.stop()

    async def _process_existing_files(self):
        """Scan watch directories for any unprocessed files."""
        for folder in self.config.watch_folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                continue

            for file_path in folder_path.iterdir():
                if (
                    file_path.is_file()
                    and file_path.suffix.lower() in ACCEPTED_EXTENSIONS
                ):
                    await self._process_file(str(file_path))

    async def _wait_for_stable_size(self, file_path: Path, timeout_sec: int = 120) -> bool:
        """
        Wait until the file size stops changing (B20 fix). A fixed delay is not
        enough for slow writes (e.g. a scanner writing to a network share).
        Returns False if the file disappeared or never stabilized.
        """
        last_size = -1
        waited = 0
        while waited < timeout_sec:
            await asyncio.sleep(SETTLE_DELAY_SEC)
            waited += SETTLE_DELAY_SEC
            try:
                size = file_path.stat().st_size
            except OSError:
                return False  # moved or deleted meanwhile
            if size == last_size:
                return True
            last_size = size
        logger.warning("File never stabilized within %ds: %s", timeout_sec, file_path)
        return False

    async def _process_file(self, file_path_str: str):
        """
        Process a single file: wait until stable, claim, ingest, move to processed.

        B20 fix — claim-by-rename: the file is renamed to '<name>.processing'
        BEFORE reading. On Windows the rename fails while a writer still holds
        the file open, which is exactly the back-off signal we need; the
        periodic sweep retries later. Only a successfully claimed file is read,
        so half-written ingests and duplicate processing cannot happen.
        """
        file_path = Path(file_path_str)

        if not file_path.exists():
            return

        if not await self._wait_for_stable_size(file_path):
            return  # gone or still growing; periodic sweep retries

        claimed_path = file_path.with_name(file_path.name + ".processing")
        try:
            file_path.rename(claimed_path)
        except OSError:
            logger.debug("File still in use, deferring: %s", file_path)
            return  # writer still holds it; periodic sweep retries

        try:
            raw_bytes = claimed_path.read_bytes()

            if not raw_bytes:
                logger.warning("Empty file, moving to processed unprocessed: %s", file_path)
                self._move_to_processed(claimed_path, original_name=file_path.name)
                return

            # Ingest
            result = await self.ingestion.ingest(
                raw_bytes=raw_bytes,
                filename=file_path.name,
                source_channel="folder",
                metadata={"source_folder": str(file_path.parent)},
            )

            if result.is_duplicate:
                logger.info("File was duplicate, moving anyway: %s", file_path.name)
            else:
                logger.info(
                    "File ingested: request_id=%s, file=%s",
                    result.request_id, file_path.name,
                )

            # Move to processed folder
            self._move_to_processed(claimed_path, original_name=file_path.name)

        except Exception:
            logger.exception("Failed to process file: %s", file_path)
            # Release the claim so the periodic sweep can retry
            try:
                claimed_path.rename(file_path)
            except OSError:
                logger.warning("Could not release claim on %s", claimed_path)

    def _move_to_processed(self, file_path: Path, original_name: str | None = None):
        """Move processed file to avoid re-processing (stored under its original name)."""
        name = original_name or file_path.name
        if self.config.processed_folder:
            dest_dir = Path(self.config.processed_folder)
        else:
            dest_dir = file_path.parent / "processed"

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name

        # Handle name collision
        if dest.exists():
            stem = Path(name).stem
            suffix = Path(name).suffix
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.move(str(file_path), str(dest))
        logger.debug("Moved to processed: %s → %s", file_path, dest)
