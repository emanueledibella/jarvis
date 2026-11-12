import Foundation

/// Bounded, source-separated daily summaries. This type has no HealthKit, network or disk access.
struct HealthSummary {
    struct Sample {
        let id: String
        let metric: String
        let source: String
        let sourceID: String
        let start: Date
        let end: Date
        let value: Double
    }
    struct Group {
        let day: String, metric: String, source: String, sourceID: String
        var total: Double = 0
        var count = 0
        var minimum = Double.greatestFiniteMagnitude
        var maximum: Double = 0
        var intervals: [(Date, Date)] = []
    }
    static let specifications: [String: (unit: String, method: String)] = [
        "steps": ("count", "sum"), "heart_rate": ("count/min", "mean"),
        "resting_heart_rate": ("count/min", "mean"), "active_energy": ("kcal", "sum"),
        "distance": ("km", "sum"), "sleep_minutes": ("min", "sum"), "workout_minutes": ("min", "sum")
    ]
    let calendar: Calendar
    let first: Date
    let collected: Date
    private let formatter: DateFormatter
    private var groups: [String: Group] = [:]
    private var seen: Set<String> = []
    private(set) var scanned = 0

    init(days: Int, timezone: TimeZone, collected: Date = Date()) throws {
        guard (1...90).contains(days) else { throw failure("Choose 1–90 days for HealthKit.") }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timezone
        self.calendar = calendar
        self.collected = collected
        first = calendar.date(byAdding: .day, value: 1 - days, to: calendar.startOfDay(for: collected))!
        formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timezone
        formatter.dateFormat = "yyyy-MM-dd"
    }

    mutating func add(_ sample: Sample) throws {
        scanned += 1
        guard scanned <= 700_000 else { throw failure("Too many HealthKit samples; choose fewer days.") }
        guard Self.specifications[sample.metric] != nil, sample.end >= sample.start,
              sample.value.isFinite, (0...1_000_000_000).contains(sample.value),
              seen.insert(sample.id).inserted else { return }
        if sample.metric == "sleep_minutes" {
            var start = max(first, sample.start)
            let end = min(collected, sample.end)
            while start < end {
                let midnight = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: start))!
                let stop = min(end, midnight)
                try append(sample, on: start, interval: (start, stop))
                start = stop
            }
        } else if sample.start >= first && sample.start <= collected {
            try append(sample, on: sample.start, interval: nil)
        }
    }

    private mutating func append(_ sample: Sample, on day: Date, interval: (Date, Date)?) throws {
        let date = formatter.string(from: day)
        let key = "\(date)|\(sample.metric)|\(sample.sourceID)"
        if groups[key] == nil {
            guard groups.count < 1500 else { throw failure("Too many daily health groups; choose fewer days.") }
            groups[key] = Group(day: date, metric: sample.metric, source: String(sample.source.prefix(100)), sourceID: sample.sourceID)
        }
        groups[key]!.count += 1
        if let interval { groups[key]!.intervals.append(interval) }
        else {
            groups[key]!.total += sample.value
            groups[key]!.minimum = min(groups[key]!.minimum, sample.value)
            groups[key]!.maximum = max(groups[key]!.maximum, sample.value)
        }
    }

    func snapshot(metrics: [String]) throws -> [String: Any] {
        let rows: [[String: Any]] = groups.keys.sorted().map { key in
            var group = groups[key]!
            let spec = Self.specifications[group.metric]!
            if !group.intervals.isEmpty {
                let intervals = group.intervals.sorted { $0.0 < $1.0 }
                var merged: [(Date, Date)] = []
                for interval in intervals {
                    if let last = merged.last, interval.0 <= last.1 {
                        merged[merged.count - 1].1 = max(last.1, interval.1)
                    } else { merged.append(interval) }
                }
                group.total = merged.reduce(0) { $0 + $1.1.timeIntervalSince($1.0) / 60 }
                group.minimum = group.total; group.maximum = group.total; group.count = 1
            }
            func rounded(_ value: Double) -> Double { (value * 1000).rounded() / 1000 }
            return ["date": group.day, "metric": group.metric, "source": group.source, "source_id": group.sourceID,
                    "unit": spec.unit, "aggregation": spec.method, "count": group.count,
                    "value": rounded(spec.method == "mean" ? group.total / Double(group.count) : group.total),
                    "min": rounded(group.minimum), "max": rounded(group.maximum)]
        }
        let result: [String: Any] = ["version": 1, "first_date": formatter.string(from: first),
                                   "last_date": formatter.string(from: collected), "timezone": calendar.timeZone.identifier,
                                   "collected_at": ISO8601DateFormatter().string(from: collected),
                                   "metrics": metrics.sorted(), "records_scanned": scanned, "rows": rows]
        guard try JSONSerialization.data(withJSONObject: result).count <= 450_000 else {
            throw failure("HealthKit preview is too large; choose fewer days or categories.")
        }
        return result
    }
}

private func failure(_ message: String) -> NSError {
    NSError(domain: "JarvisHealth", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
}
