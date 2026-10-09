from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from iot.models import SensorData, SensorReading, SensorReadingSummary
from iot.sensor_storage import aggregate_due_periods


class Command(BaseCommand):
    help = (
        'Build 30-minute summaries from existing raw readings without deleting '
        'source data. Run without --apply to preview the backlog.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Write summaries and mark processed raw rows.',
        )
        parser.add_argument(
            '--max-periods', type=int, default=500,
            help='Maximum historical periods to process in this run (default: 500).',
        )

    def handle(self, *args, **options):
        max_periods = options['max_periods']
        if max_periods < 1:
            raise CommandError('--max-periods must be at least 1')

        raw_backlog = (
            SensorReading.objects.filter(aggregation_completed_at__isnull=True).count()
            + SensorData.objects.filter(aggregation_completed_at__isnull=True).count()
        )
        self.stdout.write(
            f'Unprocessed raw rows: {raw_backlog}; existing summaries: '
            f'{SensorReadingSummary.objects.count()}'
        )
        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                'Preview only. Re-run with --apply to create summaries; no raw rows '
                'will be deleted.'
            ))
            return

        results = aggregate_due_periods(
            now=timezone.now(), backlog_periods=max_periods)
        summaries = sum(result['summaries'] for result in results)
        rows = sum(result['raw_rows'] for result in results)
        remaining = (
            SensorReading.objects.filter(aggregation_completed_at__isnull=True).count()
            + SensorData.objects.filter(aggregation_completed_at__isnull=True).count()
        )
        self.stdout.write(self.style.SUCCESS(
            f'Processed {len(results)} period(s), {rows} raw row(s), and '
            f'{summaries} summary stream(s). Remaining raw backlog: {remaining}. '
            'No raw rows were deleted.'
        ))
