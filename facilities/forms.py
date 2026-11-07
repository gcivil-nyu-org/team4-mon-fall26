from django import forms

from teams.catalog_rules import name_key
from teams.models import Sport

from .models import Facility


class NYUFacilityForm(forms.ModelForm):
    """League Admins add or edit an NYU facility. City rows come from the import."""

    # The database rejects out-of-range coordinates, so catch them here first.
    latitude = forms.DecimalField(
        required=False, min_value=-90, max_value=90, max_digits=9, decimal_places=6
    )
    longitude = forms.DecimalField(
        required=False,
        min_value=-180,
        max_value=180,
        max_digits=9,
        decimal_places=6,
        help_text="Enter both to pin this facility on the map.",
    )

    class Meta:
        model = Facility
        fields = [
            "name",
            "address",
            "borough",
            "latitude",
            "longitude",
            "sports",
            "is_active",
        ]
        labels = {"is_active": "Active"}
        help_texts = {"sports": "Hold Ctrl or Cmd to pick more than one."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.source = Facility.Source.NYU
        self.fields["sports"].queryset = Sport.objects.order_by("name")

    def clean(self):
        cleaned = super().clean()
        if "name" in cleaned and "address" in cleaned:
            if self._is_duplicate(cleaned["name"], cleaned["address"]):
                self.add_error(
                    "name", "A facility with this name and address already exists."
                )
        return cleaned

    def _is_duplicate(self, name, address):
        """Compare in Python so case and spacing are ignored alike on any database."""
        key = (name_key(name), name_key(address))
        others = Facility.objects.exclude(pk=self.instance.pk)
        return any(
            (name_key(other_name), name_key(other_address)) == key
            for other_name, other_address in others.values_list("name", "address")
        )

    def _post_clean(self):
        # Facility.clean() would repeat the required-name error and judge a
        # half-applied instance, and an invalid edit must leave the instance alone.
        if not self.errors:
            super()._post_clean()
