"""Secret-free notification failures."""

from backend.core.errors import AppError


class NotificationRouteInvalid(AppError):
    code = "NOTIFICATION_ROUTE_INVALID"
    http_status = 422


class NotificationDeliveryUnconfirmed(AppError):
    code = "NOTIFICATION_DELIVERY_UNCONFIRMED"
    http_status = 409
