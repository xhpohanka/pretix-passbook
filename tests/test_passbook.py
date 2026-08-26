import datetime
import io
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from pretix_passbook.passbook import (
    PassbookOutput,
    _first_setting_file,
    grouping_identifier,
    serial_number,
)


class Settings:
    locale = "en"
    show_date_to = True
    contact_mail = ""
    organizer_logo_image_inherit = False
    passbook_pass_type_id = "pass.example.ticket"
    passbook_team_id = "TEAM123"
    passbook_latitude = None
    passbook_longitude = None

    def get(self, key, default=None, **kwargs):
        return getattr(self, key, default)


def make_position(**changes):
    event = SimpleNamespace(
        pk=3,
        organizer_id=2,
        organizer=SimpleNamespace(name="Theatre"),
        name="Festival",
        location="Main street 1",
        date_from=datetime.datetime(2026, 8, 25, 18, tzinfo=datetime.UTC),
        date_to=datetime.datetime(2026, 8, 25, 21, tzinfo=datetime.UTC),
        date_admission=datetime.datetime(2026, 8, 25, 17, 30, tzinfo=datetime.UTC),
        timezone=datetime.UTC,
        geo_lat=None,
        geo_lon=None,
        has_subevents=True,
        seating_plan_id=None,
        get_date_from_display=lambda tz, short: "25 Aug 2026",
        get_date_to_display=lambda tz, short: "25 Aug 2026",
        settings=Settings(),
    )
    occurrence = SimpleNamespace(
        pk=4,
        name="First show",
        location="Small theatre",
        date_from=datetime.datetime(2026, 8, 26, 19, tzinfo=datetime.UTC),
        date_to=datetime.datetime(2026, 8, 26, 21, tzinfo=datetime.UTC),
        date_admission=datetime.datetime(2026, 8, 26, 18, 30, tzinfo=datetime.UTC),
        seating_plan_id=1,
        geo_lat=None,
        geo_lon=None,
        get_date_from_display=lambda tz, short: "26 Aug 2026",
        get_date_to_display=lambda tz, short: "26 Aug 2026",
    )
    order = SimpleNamespace(
        pk=9,
        code="ABCDE",
        secret="order-secret",
        event=event,
        organizer=event.organizer,
        locale="en",
        status="p",
        email="buyer@example.com",
        datetime=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )
    item = SimpleNamespace(
        name="Ticket",
        meta_data={},
        program_times=SimpleNamespace(all=lambda: []),
    )
    position = SimpleNamespace(
        pk=5,
        order=order,
        subevent=occurrence,
        subevent_id=4,
        item=item,
        variation="VIP",
        attendee_name="Ada Lovelace",
        canceled=False,
        blocked=None,
        secret="ticket-secret",
        web_secret="ticket-web-secret",
        seat_id=None,
        addon_to_id=None,
        positionid=1,
        valid_from=None,
        valid_until=None,
    )
    position.__dict__.update(changes)
    return position


class PassbookTest(SimpleTestCase):
    def test_event_artwork_is_used_as_fallback(self):
        position = make_position()
        artwork = ContentFile(b"artwork", name="event.jpg")
        position.order.event.settings.og_image = artwork

        self.assertIs(_first_setting_file(position.order.event, ["missing", "og_image"]), artwork)

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/ticket")
    @patch("pretix_passbook.passbook.get_seat")
    def test_pass_maps_ticket_data_and_current_wallet_metadata(self, get_seat, event_url):
        get_seat.return_value = SimpleNamespace(
            seat_label="7", seat_number="7", row_label="3", row_name="3", zone_name="Balcony"
        )
        position = make_position()
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        passfile = output.generate_pass(position)
        payload = passfile.json_dict()
        fields = payload["eventTicket"]

        self.assertEqual(payload["serialNumber"], "pretix-5")
        self.assertEqual(payload["groupingIdentifier"], "pretix-2-3-4-9")
        self.assertEqual(payload["barcodes"][0]["message"], "ticket-secret")
        self.assertNotIn("barcode", payload)
        self.assertEqual(fields["primaryFields"][0]["value"], "First show")
        self.assertEqual(fields["secondaryFields"][0]["value"], "Ticket - VIP")
        self.assertIn("Ada Lovelace", str(fields["backFields"]))
        self.assertIn("https://tickets.example/ticket", str(fields["backFields"]))
        event_url.assert_any_call(
            position.order.event,
            "presale:event.order.position",
            kwargs={"order": "ABCDE", "position": 1, "secret": "ticket-web-secret"},
        )

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/ticket")
    @patch("pretix_passbook.passbook.get_seat")
    def test_regular_event_uses_event_data(self, get_seat, event_url):
        position = make_position(subevent=None, subevent_id=None)
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        payload = output.generate_pass(position).json_dict()

        self.assertEqual(payload["eventTicket"]["primaryFields"][0]["value"], "Festival")
        self.assertEqual(payload["relevantDate"], "2026-08-25T17:30:00+00:00")

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/ticket")
    def test_serial_is_unchanged_when_order_code_changes(self, event_url):
        position = make_position()
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        first = serial_number(position)
        position.order.code = "CHANGED"
        self.assertEqual(first, serial_number(position))
        self.assertEqual(grouping_identifier(position), "pretix-2-3-4-9")

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/ticket")
    def test_canceled_pass_is_voided(self, event_url):
        position = make_position(canceled=True)
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        self.assertTrue(output.generate_pass(position).json_dict()["voided"])

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/ticket")
    def test_expired_pass_has_expiration_and_is_voided(self, event_url):
        position = make_position(valid_until=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC))
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        payload = output.generate_pass(position).json_dict()

        self.assertEqual(payload["expirationDate"], "2026-08-01T00:00:00+00:00")
        self.assertTrue(payload["voided"])

    def test_order_download_is_a_standard_zip_of_pkpasses(self):
        output = PassbookOutput.__new__(PassbookOutput)
        position = make_position()
        second = make_position(pk=6, positionid=2)
        order = SimpleNamespace(code="ABCDE", positions_with_tickets=[position, second])
        output.get_tickets_to_print = lambda current_order: current_order.positions_with_tickets
        output.generate_file = lambda current_position: (
            "ticket.pkpass", "application/vnd.apple.pkpass", current_position.pk.to_bytes(1, "big")
        )

        filename, content_type, content = output.generate_order_file(order)

        self.assertEqual(filename, "ABCDE-passbook.pkpasses")
        self.assertEqual(content_type, "application/vnd.apple.pkpasses")
        with ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), ["ABCDE-1.pkpass", "ABCDE-2.pkpass"])

    @patch("pretix_passbook.passbook.eventreverse_absolute", return_value="https://tickets.example/pass")
    def test_download_is_generated_by_an_on_demand_url(self, event_url):
        position = make_position()
        output = PassbookOutput.__new__(PassbookOutput)
        output.event = position.order.event

        self.assertEqual(output.generate(position)[1:], ("text/uri-list", "https://tickets.example/pass"))
        event_url.assert_called_once_with(
            position.order.event,
            "plugins:pretix_passbook:save",
            kwargs={"order": "ABCDE", "secret": "order-secret", "position": 5},
        )
