import EventKit
import Foundation

@MainActor
final class CalendarBridge {
    private let store = EKEventStore()
    private let formatter = ISO8601DateFormatter()

    func authorize() async throws -> [String: Any] {
        let granted = try await store.requestFullAccessToEvents()
        return ["state": granted ? "authorized" : "denied"]
    }

    func perform(_ operation: String, _ arguments: [String: Any]) throws -> [String: Any] {
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else {
            throw ServiceClient.ClientError.server("Grant calendar access in Jarvis settings.")
        }
        if operation == "calendar.list" {
            let days = min(max(arguments["days"] as? Int ?? 7, 1), 30)
            let end = Calendar.current.date(byAdding: .day, value: days, to: Date())!
            let predicate = store.predicateForEvents(withStart: Date(), end: end, calendars: nil)
            let events = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }.prefix(200)
            let rows: [[String: Any]] = events.map { event in
                ["id": event.eventIdentifier ?? "", "title": event.title ?? "Event", "start": formatter.string(from: event.startDate), "end": formatter.string(from: event.endDate), "all_day": event.isAllDay, "location": event.location ?? "", "calendar": event.calendar.title, "calendar_id": event.calendar.calendarIdentifier]
            }
            return ["state": "ready", "provider": "apple", "events": rows, "updated_at": formatter.string(from: Date())]
        }
        if operation == "calendar.delete" {
            guard let key = arguments["event_id"] as? String, let event = store.event(withIdentifier: key) else {
                throw ServiceClient.ClientError.server("Event not found; refresh the calendar.")
            }
            // Only the selected occurrence is deleted. A whole series is never removed by inference.
            try store.remove(event, span: .thisEvent, commit: true)
            return ["state": "completed", "event_id": key]
        }
        let values = arguments["event"] as? [String: Any] ?? arguments
        guard let title = values["title"] as? String,
              let startValue = values["start"] as? String, let start = parseDate(startValue),
              let endValue = values["end"] as? String, let end = parseDate(endValue), end > start else {
            throw ServiceClient.ClientError.server("Invalid event title or dates.")
        }
        let event: EKEvent
        if operation == "calendar.update", let key = arguments["event_id"] as? String, let existing = store.event(withIdentifier: key) {
            event = existing
        } else if operation == "calendar.create" {
            event = EKEvent(eventStore: store)
            event.calendar = store.defaultCalendarForNewEvents
        } else {
            throw ServiceClient.ClientError.server("Unsupported calendar operation or missing event.")
        }
        event.title = title
        event.startDate = start
        event.endDate = end
        event.location = values["location"] as? String
        event.notes = values["notes"] as? String
        try store.save(event, span: .thisEvent, commit: true)
        return ["state": "completed", "event": ["id": event.eventIdentifier ?? "", "title": title, "start": formatter.string(from: start), "end": formatter.string(from: end)]]
    }

    private func parseDate(_ value: String) -> Date? {
        if let result = formatter.date(from: value) { return result }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value)
    }
}
