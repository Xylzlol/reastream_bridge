#include "PluginEditor.h"

NetStreamReceiverEditor::NetStreamReceiverEditor (NetStreamReceiverProcessor& p)
    : AudioProcessorEditor (p), proc (p)
{
    setSize (320, 160);
    startTimerHz (10); // 10 fps refresh
}

void NetStreamReceiverEditor::timerCallback()
{
    fillFrames = proc.bufferFillFrames.load();
    capacity   = proc.bufferCapacityFrames.load();
    packets    = proc.getReceiver().packetsReceived.load();
    dropped    = proc.getReceiver().packetsDropped.load();
    underruns  = proc.underrunCount.load();
    sampleRate = proc.getReceiver().lastSampleRate.load();

    repaint();
}

void NetStreamReceiverEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour (0xff1e1e2e)); // dark background

    g.setFont (juce::FontOptions (14.0f));

    // Title
    g.setColour (juce::Colour (0xffcdd6f4));
    g.drawText ("NetStream Receiver", getLocalBounds().removeFromTop (28),
                juce::Justification::centred);

    // Stats
    g.setFont (juce::FontOptions (12.0f));
    auto area = getLocalBounds().reduced (12, 0).withTrimmedTop (32);
    const int lineH = 18;

    auto line = [&] (const juce::String& label, const juce::String& value,
                     juce::Colour valColour = juce::Colour (0xffa6e3a1))
    {
        auto row = area.removeFromTop (lineH);
        g.setColour (juce::Colour (0xff9399b2));
        g.drawText (label, row, juce::Justification::left);
        g.setColour (valColour);
        g.drawText (value, row, juce::Justification::right);
    };

    float fillPct = capacity > 0 ? 100.0f * fillFrames / capacity : 0.0f;
    float fillMs  = sampleRate > 0 ? 1000.0f * fillFrames / sampleRate : 0.0f;

    line ("Buffer",     juce::String (fillMs, 1) + " ms (" + juce::String (fillPct, 0) + "%)");
    line ("Packets",    juce::String (packets));
    line ("Dropped",    juce::String (dropped),
          dropped > 0 ? juce::Colour (0xfff38ba8) : juce::Colour (0xffa6e3a1));
    line ("Underruns",  juce::String (underruns),
          underruns > 0 ? juce::Colour (0xfff38ba8) : juce::Colour (0xffa6e3a1));
    line ("Sample Rate", sampleRate > 0 ? juce::String (sampleRate) + " Hz" : "---");
    line ("Port",       juce::String (NetStreamReceiverProcessor::DEFAULT_PORT));
}
