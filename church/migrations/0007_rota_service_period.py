from django.db import migrations, models


def use_service_start_as_period_end(apps, schema_editor):
    Rota = apps.get_model("church", "Rota")
    Rota.objects.all().update(service_until=models.F("service_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("church", "0006_rota_service_occurrence"),
    ]

    operations = [
        migrations.AddField(
            model_name="rota",
            name="service_until",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(use_service_start_as_period_end, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rota",
            name="service_until",
            field=models.DateTimeField(),
        ),
        migrations.AddConstraint(
            model_name="rota",
            constraint=models.CheckConstraint(condition=models.Q(service_until__gte=models.F("service_at")),
                                              name="rota_period_end_after_start"),
        ),
    ]
