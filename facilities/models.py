from django.core.exceptions import ValidationError
from django.db import models

from teams.catalog_rules import normalize_name


class Facility(models.Model):
    """A place where matches are played: a city facility from NYC Open Data or an NYU one."""

    class Source(models.TextChoices):
        CITY = "city", "NYC Open Data"
        NYU = "nyu", "NYU"

    class Borough(models.TextChoices):
        MANHATTAN = "manhattan", "Manhattan"
        BROOKLYN = "brooklyn", "Brooklyn"
        QUEENS = "queens", "Queens"
        BRONX = "bronx", "Bronx"
        STATEN_ISLAND = "staten_island", "Staten Island"

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    borough = models.CharField(max_length=20, choices=Borough.choices, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    sports = models.ManyToManyField(
        "teams.Sport", blank=True, related_name="facilities"
    )
    source = models.CharField(max_length=10, choices=Source.choices)
    # The dataset's own ID for city facilities, so re-running the import updates
    # rows instead of duplicating them. Empty for NYU facilities.
    external_id = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(
        default=True, help_text="Inactive facilities can't be picked for new matches."
    )

    class Meta:
        verbose_name_plural = "facilities"
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_facility_external_id_per_source",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90, latitude__lte=90)
                | models.Q(latitude__isnull=True),
                name="facility_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__gte=-180, longitude__lte=180)
                | models.Q(longitude__isnull=True),
                name="facility_longitude_range",
            ),
        ]

    def clean(self):
        self.name = normalize_name(self.name or "")
        self.address = normalize_name(self.address or "")
        if not self.name:
            raise ValidationError({"name": "Enter a name."})
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError(
                "Enter both latitude and longitude, or leave both empty."
            )
        if self.source == self.Source.CITY and not self.external_id:
            raise ValidationError(
                {"external_id": "City facilities need their dataset ID."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def __str__(self):
        return self.name
