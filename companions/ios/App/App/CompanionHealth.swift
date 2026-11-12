import Foundation
import HealthKit
import CryptoKit
import UIKit

/// Foreground, read-only HealthKit access. No raw samples are persisted or sent over the network.
@MainActor final class CompanionHealth {
    private lazy var store = HKHealthStore()
    private var reading = false
    private var generation = UUID()
    private var queries: [UUID: (HKQuery, (Result<[HKSample], Error>) -> Void)] = [:]

    static var available: Bool { HKHealthStore.isHealthDataAvailable() }

    func cancel() {
        generation = UUID()
        let pending = queries
        queries.removeAll()
        for (_, (query, finish)) in pending {
            store.stop(query)
            finish(.failure(error("HealthKit reading cancelled. Open Jarvis and try again.")))
        }
    }

    func read(metrics: [String], days: Int) async throws -> [String: Any] {
        guard Self.available else { throw error("Apple Health is unavailable on this device.") }
        guard !reading, UIApplication.shared.applicationState == .active else {
            throw error("Open Jarvis and wait for the current HealthKit reading to finish.")
        }
        guard !metrics.isEmpty, metrics.count <= 7, Set(metrics).count == metrics.count,
              metrics.allSatisfy({ HealthSummary.specifications[$0] != nil }) else {
            throw error("Choose at least one supported health category.")
        }
        var summary = try HealthSummary(days: days, timezone: .current)
        reading = true
        defer { reading = false }
        let boundary = generation
        let readTypes = Set(metrics.compactMap { sampleType($0) as HKObjectType? })
        // Completion means the sheet was handled, never that all read permissions were granted.
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            store.requestAuthorization(toShare: [], read: readTypes) { success, failure in
                if let failure { continuation.resume(throwing: failure) }
                else if !success { continuation.resume(throwing: self.error("HealthKit authorization request could not be completed.")) }
                else { continuation.resume() }
            }
        }
        guard generation == boundary, UIApplication.shared.applicationState != .background else {
            throw error("HealthKit reading cancelled. Open Jarvis and try again.")
        }
        for metric in metrics.sorted() {
            guard let type = sampleType(metric) else { continue }
            let predicate = HKQuery.predicateForSamples(withStart: summary.first, end: summary.collected)
            let samples = try await samples(type: type, predicate: predicate)
            guard generation == boundary, UIApplication.shared.applicationState != .background else {
                throw error("HealthKit reading cancelled. Open Jarvis and try again.")
            }
            guard samples.count <= 100_000 else { throw error("Too many HealthKit samples; choose fewer days.") }
            for (index, sample) in samples.enumerated() {
                if index % 1024 == 0 {
                    await Task.yield()
                    guard generation == boundary else { throw error("HealthKit reading cancelled. Open Jarvis and try again.") }
                }
                let value: Double
                if let quantity = sample as? HKQuantitySample {
                    value = quantity.quantity.doubleValue(for: unit(metric))
                } else if let category = sample as? HKCategorySample {
                    // Values 1 = asleep/unspecified, 3/4/5 = core/deep/REM (iOS 16+).
                    guard [1, 3, 4, 5].contains(category.value) else { continue }
                    value = 0
                } else if let workout = sample as? HKWorkout { value = workout.duration / 60 }
                else { continue }
                let source = sample.sourceRevision.source
                let device = sample.device
                let descriptor = [source.bundleIdentifier, device?.localIdentifier ?? "", device?.name ?? "", device?.model ?? ""].joined(separator: "|")
                let sourceID = SHA256.hash(data: Data(descriptor.utf8)).prefix(12).map { String(format: "%02x", $0) }.joined()
                let label = source.name + (device?.model.map { " · " + $0 } ?? "")
                try summary.add(.init(id: sample.uuid.uuidString, metric: metric, source: label, sourceID: sourceID,
                                      start: sample.startDate, end: sample.endDate, value: value))
            }
        }
        return try summary.snapshot(metrics: metrics)
    }

    private func samples(type: HKSampleType, predicate: NSPredicate) async throws -> [HKSample] {
        try await withCheckedThrowingContinuation { continuation in
            let id = UUID()
            let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: 100_001,
                                      sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]) { [weak self] _, values, failure in
                DispatchQueue.main.async {
                    self?.finish(id, failure.map { .failure($0) } ?? .success(values ?? []))
                }
            }
            queries[id] = (query, { continuation.resume(with: $0) })
            store.execute(query)
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
                guard let self, let pending = self.queries[id] else { return }
                self.store.stop(pending.0)
                self.finish(id, .failure(self.error("HealthKit reading timed out; choose fewer days.")))
            }
        }
    }

    private func finish(_ id: UUID, _ result: Result<[HKSample], Error>) {
        queries.removeValue(forKey: id)?.1(result)
    }

    private func sampleType(_ metric: String) -> HKSampleType? {
        switch metric {
        case "steps": return HKObjectType.quantityType(forIdentifier: .stepCount)
        case "heart_rate": return HKObjectType.quantityType(forIdentifier: .heartRate)
        case "resting_heart_rate": return HKObjectType.quantityType(forIdentifier: .restingHeartRate)
        case "active_energy": return HKObjectType.quantityType(forIdentifier: .activeEnergyBurned)
        case "distance": return HKObjectType.quantityType(forIdentifier: .distanceWalkingRunning)
        case "sleep_minutes": return HKObjectType.categoryType(forIdentifier: .sleepAnalysis)
        case "workout_minutes": return HKObjectType.workoutType()
        default: return nil
        }
    }

    private func unit(_ metric: String) -> HKUnit {
        switch metric {
        case "heart_rate", "resting_heart_rate": return HKUnit.count().unitDivided(by: .minute())
        case "active_energy": return .kilocalorie()
        case "distance": return .meterUnit(with: .kilo)
        default: return .count()
        }
    }

    private nonisolated func error(_ message: String) -> NSError {
        NSError(domain: "JarvisHealth", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
