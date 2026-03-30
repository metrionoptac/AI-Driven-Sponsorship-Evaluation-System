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

    async def _process_file(self, file_path_str: str):
        """Process a single file: read, ingest, move to processed."""
        file_path = Path(file_path_str)

        if not file_path.exists():
            return

        # Wait for file write to complete
        await asyncio.sleep(SETTLE_DELAY_SEC)

        # Double-check file still exists (might have been moved)
        if not file_path.exists():
            return

        try:
            # Read file bytes
            raw_bytes = file_path.read_bytes()

            if not raw_bytes:
                logger.warning("Empty file, skipping: %s", file_path)
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
            self._move_to_processed(file_path)

        except Exception:
            logger.exception("Failed to process file: %s", file_path)

    def _move_to_processed(self, file_path: Path):
        """Move processed file to avoid re-processing."""
        if self.config.processed_folder:
            dest_dir = Path(self.config.processed_folder)
        else:
            dest_dir = file_path.parent / "processed"

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / file_path.name

        # Handle name collision
        if dest.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.move(str(file_path), str(dest))
        logger.debug("Moved to processed: %s → %s", file_path, dest)
