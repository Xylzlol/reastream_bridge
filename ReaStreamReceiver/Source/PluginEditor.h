#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "PluginProcessor.h"

class ReaStreamReceiverEditor : public juce::AudioProcessorEditor,
                                 private juce::Timer
{
public:
    explicit ReaStreamReceiverEditor (ReaStreamReceiverProcessor&);
    ~ReaStreamReceiverEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override {}

private:
    void timerCallback() override;

    ReaStreamReceiverProcessor& proc;

    // Cached stats for display
    int    fillFrames   = 0;
    int    capacity     = 0;
    uint64_t packets    = 0;
    uint64_t dropped    = 0;
    uint64_t underruns  = 0;
    int    sampleRate   = 0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ReaStreamReceiverEditor)
};
