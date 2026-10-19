from django import forms
from django.contrib.auth import get_user_model


class ProfileForm(forms.ModelForm):
    """Fields a user may edit on their own profile.

    Email, verification status and roles are deliberately left out.
    TODO(T13): confirm the editable fields; switch to display_name when T3 lands.
    """

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True
