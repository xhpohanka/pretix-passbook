from io import BytesIO

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views import View
from pretix.base.models import OrderPosition
from pretix.base.timemachine import time_machine_now
from pretix.presale.views import EventViewMixin
from pretix.presale.views.order import OrderDetailMixin

from .passbook import PassbookOutput


def wallet_positions(order):
    now = time_machine_now()
    return [
        position for position in order.positions_with_tickets
        if not position.canceled
        and not position.blocked
        and (not position.valid_until or position.valid_until > now)
    ]


def check_download_available(request, order):
    if not PassbookOutput(request.event).is_enabled or not order.ticket_download_available:
        raise Http404("Ticket download is not available.")
    if (
        request.event.settings.ticket_download_require_validated_email
        and order.sales_channel.type == "web"
        and not order.email_known_to_work
    ):
        raise Http404("Ticket download is not available.")


class PassbookSaveView(EventViewMixin, OrderDetailMixin, View):
    def get(self, request, *args, **kwargs):
        check_download_available(request, self.order)
        position = get_object_or_404(
            OrderPosition.objects.select_related(
                "order", "order__event", "order__event__organizer", "item", "subevent",
            ),
            order=self.order,
            pk=kwargs["position"],
        )
        if position not in wallet_positions(self.order):
            raise Http404("Ticket download is not available.")
        filename, content_type, content = PassbookOutput(request.event).generate_file(position)
        return FileResponse(
            BytesIO(content), as_attachment=True, filename=filename, content_type=content_type
        )


class PassbookSaveAllView(EventViewMixin, OrderDetailMixin, View):
    def get(self, request, *args, **kwargs):
        check_download_available(request, self.order)
        positions = wallet_positions(self.order)
        if len(positions) < 2:
            raise Http404("Ticket download is not available.")
        filename, content_type, content = PassbookOutput(request.event).generate_order_file(
            self.order, positions
        )
        return FileResponse(
            BytesIO(content), as_attachment=True, filename=filename, content_type=content_type
        )
