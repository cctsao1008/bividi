#include "bividi/replay.hpp"

#include <deque>
#include <stdexcept>
#include <utility>
#include <vector>

namespace bividi {

struct InterceptedReplaySource::Impl {
    Impl(
        ReplaySource replay_source,
        std::shared_ptr<ReplayObservationInterceptor> replay_interceptor)
        : source(std::move(replay_source)), interceptor(std::move(replay_interceptor)) {
        if (!interceptor) {
            throw std::invalid_argument("InterceptedReplaySource requires an interceptor");
        }
        interceptor->reset();
    }

    void enqueue(std::vector<SensorObservation>& emitted) {
        for (auto& observation : emitted) {
            pending.push_back(std::move(observation));
        }
    }

    bool fill() {
        while (pending.empty()) {
            if (!source.eof()) {
                const auto source_index = source.position();
                SensorObservation observation;
                if (!source.next(observation)) {
                    continue;
                }

                std::vector<SensorObservation> emitted;
                interceptor->transform(source_index, std::move(observation), emitted);
                enqueue(emitted);
                continue;
            }

            if (!flushed) {
                std::vector<SensorObservation> emitted;
                interceptor->flush(emitted);
                flushed = true;
                enqueue(emitted);
                continue;
            }
            return false;
        }
        return true;
    }

    ReplaySource source;
    std::shared_ptr<ReplayObservationInterceptor> interceptor;
    std::deque<SensorObservation> pending;
    bool flushed = false;
};

InterceptedReplaySource::InterceptedReplaySource(
    ReplaySource source,
    std::shared_ptr<ReplayObservationInterceptor> interceptor)
    : impl_(std::make_unique<Impl>(std::move(source), std::move(interceptor))) {}

InterceptedReplaySource::~InterceptedReplaySource() = default;
InterceptedReplaySource::InterceptedReplaySource(InterceptedReplaySource&&) noexcept = default;
InterceptedReplaySource& InterceptedReplaySource::operator=(InterceptedReplaySource&&) noexcept = default;

const SensorCapabilities& InterceptedReplaySource::capabilities() const noexcept {
    return impl_->source.capabilities();
}

const ReplayMetadata& InterceptedReplaySource::metadata() const noexcept {
    return impl_->source.metadata();
}

std::size_t InterceptedReplaySource::source_size() const noexcept {
    return impl_->source.size();
}

std::size_t InterceptedReplaySource::source_position() const noexcept {
    return impl_->source.position();
}

bool InterceptedReplaySource::eof() const noexcept {
    return impl_->source.eof() && impl_->pending.empty() && impl_->flushed;
}

bool InterceptedReplaySource::next(SensorObservation& out) {
    if (!impl_->fill()) {
        out = {};
        return false;
    }
    out = std::move(impl_->pending.front());
    impl_->pending.pop_front();
    return true;
}

void InterceptedReplaySource::reset() {
    impl_->source.reset();
    impl_->pending.clear();
    impl_->flushed = false;
    impl_->interceptor->reset();
}

}  // namespace bividi
