from django.core.management.base import BaseCommand, CommandError

from iot.sensor_storage import cleanup_aggregated_raw_data


class Command(BaseCommand):
    help = (
        'Delete raw sensor rows that are older than retention and already '
        'processed. Latest device readings are always preserved.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Run once even when scheduled cleanup is disabled.',
        )
        parser.add_argument('--batch-size', type=int, default=5000)

    def handle(self, *args, **options):
        if options['batch_size'] < 1:
            raise CommandError('--batch-size must be at least 1')
        result = cleanup_aggregated_raw_data(
            batch_size=options['batch_size'], force=options['force'])
        if not result['enabled']:
            self.stdout.write(self.style.WARNING(
                'Cleanup is disabled. Verify summaries, then enable it in '
                'Administrator > Sensor Storage Settings or use --force once.'
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {result['deleted']} eligible raw row(s); retention is "
            f"{result['retention_days']} days. Summaries and latest readings remain."
        ))
