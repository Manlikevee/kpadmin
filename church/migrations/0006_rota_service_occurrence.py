from django.db import migrations, models
import django.db.models.deletion


def copy_event_start_to_rota_service_at(apps, schema_editor):
    Rota = apps.get_model("church", "Rota")
    for rota in Rota.objects.select_related("event").iterator():
        rota.service_at = rota.event.start_at
        rota.save(update_fields=["service_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("church", "0005_pastor_photo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rota",
            name="event",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rotas", to="church.event"),
        ),
        migrations.AddField(
            model_name="rota",
            name="service_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(copy_event_start_to_rota_service_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rota",
            name="service_at",
            field=models.DateTimeField(),
        ),
        migrations.AlterModelOptions(
            name="rota",
            options={"ordering": ["service_at"]},
        ),
        migrations.AddConstraint(
            model_name="rota",
            constraint=models.UniqueConstraint(fields=("event", "service_at", "branch"), name="uniq_rota_event_date_branch"),
        ),
    ]
