import Foundation

@main struct HealthSummaryTests {
    static func main() throws {
        let iso = ISO8601DateFormatter()
        func date(_ text: String) -> Date { iso.date(from: text)! }
        let zone = TimeZone(identifier: "Europe/Rome")!
        let now = date("2026-10-26T12:00:00Z")
        var summary = try HealthSummary(days: 3, timezone: zone, collected: now)
        func sample(_ id: String, _ metric: String = "steps", source: String = "111111111111111111111111", start: String = "2026-10-25T12:00:00Z", end: String = "2026-10-25T12:01:00Z", value: Double = 100) -> HealthSummary.Sample {
            .init(id: id, metric: metric, source: "Same visible name", sourceID: source, start: date(start), end: date(end), value: value)
        }
        try summary.add(sample("step"))
        try summary.add(sample("step"))
        try summary.add(sample("watch", source: "222222222222222222222222", value: 200))
        try summary.add(sample("heart-1", "heart_rate", value: 70))
        try summary.add(sample("heart-2", "heart_rate", value: 90))
        // The DST transition night is five actual hours from local midnight to 04:00.
        try summary.add(sample("sleep-1", "sleep_minutes", start: "2026-10-24T22:00:00Z", end: "2026-10-25T03:00:00Z", value: 0))
        try summary.add(sample("sleep-2", "sleep_minutes", start: "2026-10-25T00:00:00Z", end: "2026-10-25T02:00:00Z", value: 0))
        try summary.add(sample("old", start: "2026-10-21T12:00:00Z", end: "2026-10-21T12:01:00Z"))
        try summary.add(sample("invalid", value: .nan))
        let snapshot = try summary.snapshot(metrics: ["steps", "heart_rate", "sleep_minutes"])
        let rows = snapshot["rows"] as! [[String: Any]]
        let steps = rows.filter { $0["metric"] as? String == "steps" }
        precondition(steps.count == 2)
        precondition(Set(steps.map { $0["value"] as! Double }) == Set([100.0, 200.0]))
        let heart = rows.first { $0["metric"] as? String == "heart_rate" }!
        precondition(heart["value"] as! Double == 80 && heart["min"] as! Double == 70 && heart["max"] as! Double == 90)
        precondition(heart["count"] as! Int == 2)
        precondition(rows.first { $0["metric"] as? String == "sleep_minutes" }!["value"] as! Double == 300)
        precondition(snapshot["first_date"] as! String == "2026-10-24")
        var midnight = try HealthSummary(days: 1, timezone: zone, collected: now)
        try midnight.add(sample("cross-midnight", "sleep_minutes", start: "2026-10-25T22:00:00Z", end: "2026-10-26T02:00:00Z", value: 0))
        let today = try midnight.snapshot(metrics: ["sleep_minutes"])["rows"] as! [[String: Any]]
        precondition(today.count == 1 && today[0]["value"] as! Double == 180)
        let empty = try HealthSummary(days: 1, timezone: zone, collected: now).snapshot(metrics: ["steps"])
        precondition((empty["rows"] as! [[String: Any]]).isEmpty)
        do { _ = try HealthSummary(days: 91, timezone: zone); preconditionFailure("Unbounded window accepted") }
        catch { }
        // Optional argument writes the exact native bridge contract for an API round-trip fixture.
        if CommandLine.arguments.count > 1 {
            var fresh = try HealthSummary(days: 7, timezone: zone)
            let instant = Date().addingTimeInterval(-60)
            try fresh.add(.init(id: "fixture", metric: "steps", source: "Synthetic iPhone", sourceID: "111111111111111111111111", start: instant, end: instant, value: 4321))
            try JSONSerialization.data(withJSONObject: fresh.snapshot(metrics: ["steps"])).write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        }
        print("Health summary: 10 scenarios passed (sources, duplicates, mean, DST, midnight, limits, empty reads)")
    }
}
