from rest_framework.permissions import BasePermission

from marketplace.auth import has_farm_access


class HasActiveFarmAccess(BasePermission):
    message = "An active GoHMoTech farm role is required."

    def has_permission(self, request, view):
        return bool(request.user.is_active and has_farm_access(request.user))
