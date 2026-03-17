#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "LockFreeRingBuffer.h"
#include "UdpReceiver.h"

class ReaStreamReceiverProcessor : public juce::AudioProcessor
{
public:
    ReaStreamReceiverProcessor();
    ~ReaStreamReceiverProcessor() override;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "ReaStream Receiver"; }
    bool acceptsMidi()  const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms()    override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    // --- Public state for the editor ---
    std::atomic<int> bufferFillFrames { 0 };
    std::atomic<int> bufferCapacityFrames { 0 };
    std::atomic<uint64_t> underrunCount { 0 };

    UdpReceiver& getReceiver() { return receiver; }

    // Parameters
    static constexpr int DEFAULT_PORT = 58710;
    static constexpr int JITTER_BUFFER_MS = 4; // ~176 frames at 44.1k

private:
    // Ring buffer sized for jitter absorption
    LockFreeRingBuffer ringBuffer { 1, 2 };
    UdpReceiver receiver { ringBuffer };

    int jitterBufferFrames = 0;
    bool primed = false; // wait until jitter buffer is filled before outputting

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ReaStreamReceiverProcessor)
};
