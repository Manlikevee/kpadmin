from datetime import timedelta

from django.db import migrations, models


def set_six_hour_duration(apps, schema_editor):
    Rota = apps.get_model("church", "Rota")
    for rota in Rota.objects.only("pk", "service_at").iterator():
        Rota.objects.filter(pk=rota.pk).update(service_until=rota.service_at + timedelta(hours=6))


class Migration(migrations.Migration):

    dependencies = [("church", "0007_rota_service_period")]

    operations = [
        migrations.RunPython(set_six_hour_duration, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rota",
            name="service_until",
            field=models.DateTimeField(),
        ),
    ]
