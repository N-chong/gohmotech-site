from rest_framework.permissions import BasePermission

from marketplace.auth import can_manage_farm



class HasActiveFarmAccess(BasePermission):
    message = "An active GoHMoTech farm owner role is required."

    def has_permission(self, request, view):
        return bool(request.user.is_active and can_manage_farm(request.user))
