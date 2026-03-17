#pragma once
#include <atomic>
#include <cstring>
#include <vector>

/**
 * Single-producer, single-consumer lock-free ring buffer for audio samples.
 *
 * Layout: non-interleaved channels stored contiguously per frame.
 *   [frame0_ch0, frame0_ch1, frame1_ch0, frame1_ch1, ...]
 *
 * The network thread writes, the audio thread reads.  No locks, no allocations
 * on the hot path — just atomic load/store with acquire/release ordering.
 */
class LockFreeRingBuffer
{
public:
    LockFreeRingBuffer (int capacityFrames, int numChannels)
        : capacity (capacityFrames),
          channels (numChannels),
          buffer (static_cast<size_t> (capacityFrames) * numChannels, 0.0f)
    {
    }

    void resize (int capacityFrames, int numChannels)
    {
        capacity = capacityFrames;
        channels = numChannels;
        buffer.assign (static_cast<size_t> (capacityFrames) * numChannels, 0.0f);
        readPos.store (0, std::memory_order_relaxed);
        writePos.store (0, std::memory_order_relaxed);
    }

    /** Write interleaved frames from the network thread. */
    void writeFrames (const float* data, int numFrames)
    {
        auto w = writePos.load (std::memory_order_relaxed);

        for (int i = 0; i < numFrames; ++i)
        {
            auto* dest = &buffer[static_cast<size_t> (w) * channels];
            std::memcpy (dest, data + static_cast<size_t> (i) * channels,
                         sizeof (float) * channels);

            w = (w + 1) % capacity;
        }

        writePos.store (w, std::memory_order_release);
    }

    /** Write non-interleaved (per-channel) data — matches ReaStream wire format.
     *  src layout: [ch0_sample0, ch0_sample1, ..., ch1_sample0, ch1_sample1, ...]
     */
    void writeNonInterleaved (const float* src, int numFrames, int srcChannels)
    {
        auto w = writePos.load (std::memory_order_relaxed);
        const int ch = (std::min) (srcChannels, channels);

        for (int i = 0; i < numFrames; ++i)
        {
            auto* dest = &buffer[static_cast<size_t> (w) * channels];

            for (int c = 0; c < ch; ++c)
                dest[c] = src[c * numFrames + i];

            // Zero any extra channels we have but the source doesn't
            for (int c = ch; c < channels; ++c)
                dest[c] = 0.0f;

            w = (w + 1) % capacity;
        }

        writePos.store (w, std::memory_order_release);
    }

    /** Read frames into separate per-channel output buffers (JUCE processBlock style).
     *  Returns actual frames read (may be less than requested if buffer is sparse). */
    int readFrames (float** channelPtrs, int numFrames)
    {
        auto r = readPos.load (std::memory_order_relaxed);
        const auto w = writePos.load (std::memory_order_acquire);

        const int avail = available (r, w);
        const int toRead = (std::min) (numFrames, avail);

        for (int i = 0; i < toRead; ++i)
        {
            const auto* src = &buffer[static_cast<size_t> (r) * channels];

            for (int c = 0; c < channels; ++c)
                channelPtrs[c][i] = src[c];

            r = (r + 1) % capacity;
        }

        // Zero-fill remainder if we didn't have enough
        for (int i = toRead; i < numFrames; ++i)
            for (int c = 0; c < channels; ++c)
                channelPtrs[c][i] = 0.0f;

        readPos.store (r, std::memory_order_release);
        return toRead;
    }

    int getAvailable() const
    {
        return available (readPos.load (std::memory_order_acquire),
                          writePos.load (std::memory_order_acquire));
    }

    int getCapacity() const { return capacity; }
    int getChannels() const { return channels; }

    void reset()
    {
        readPos.store (0, std::memory_order_relaxed);
        writePos.store (0, std::memory_order_relaxed);
    }

private:
    int available (int r, int w) const
    {
        if (w >= r)
            return w - r;
        return capacity - r + w;
    }

    int capacity = 0;
    int channels = 0;
    std::vector<float> buffer;
    std::atomic<int> readPos { 0 };
    std::atomic<int> writePos { 0 };
};
