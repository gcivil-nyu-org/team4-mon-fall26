"""Who a NetID belongs to (#304).

NYU emails are usually netid@nyu.edu, and an active account has confirmed its
email. So a NetID belongs first to the active account with that email. Nobody
else can take it, and that account gets it back from anyone who did.
"""

from django.contrib.auth import get_user_model

from .models import PlayerProfile

NYU_DOMAIN = "@nyu.edu"


def owns_net_id(user, net_id):
    return user.email.lower() == f"{net_id}{NYU_DOMAIN}"


def belongs_to_someone_else(net_id, user):
    """True when another active account's email is this NetID."""
    return (
        get_user_model()
        .objects.filter(email__iexact=f"{net_id}{NYU_DOMAIN}", is_active=True)
        .exclude(pk=user.pk)
        .exists()
    )


def release_net_id(net_id, owner):
    """Take a NetID off any other profile. Call only for its owner."""
    PlayerProfile.objects.filter(net_id=net_id).exclude(user=owner).update(net_id=None)
