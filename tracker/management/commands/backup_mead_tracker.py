from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tracker.services.backups import BackupError, create_backup_file


class Command(BaseCommand):
    help = "Create a verified SQLite backup using SQLite's online backup API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--destination",
            type=Path,
            help="Directory for the snapshot; defaults to MEAD_TRACKER_BACKUP_DIR.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=30,
            help="Number of dated Mead Tracker snapshots to retain (default: 30).",
        )

    def handle(self, *args, **options):
        try:
            keep = options["keep"]
            if keep < 1:
                raise CommandError("--keep must be at least 1.")
            target = create_backup_file(options.get("destination"))
        except BackupError as exc:
            raise CommandError(str(exc)) from exc

        snapshots = sorted(
            target.parent.glob("mead-tracker-*.sqlite3"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_snapshot in snapshots[keep:]:
            old_snapshot.unlink()
        self.stdout.write(self.style.SUCCESS(f"Backup created: {target}"))
