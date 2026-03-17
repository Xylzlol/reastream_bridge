#include "PluginProcessor.h"
#include "PluginEditor.h"

ReaStreamReceiverProcessor::ReaStreamReceiverProcessor()
    : AudioProcessor (BusesProperties()
                        .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
}

ReaStreamReceiverProcessor::~ReaStreamReceiverProcessor()
{
    receiver.stop();
}

void ReaStreamReceiverProcessor::prepareToPlay (double sampleRate, int /*samplesPerBlock*/)
{
    // Size jitter buffer: JITTER_BUFFER_MS worth of frames, minimum 256
    jitterBufferFrames = (std::max) (256, static_cast<int> (sampleRate * JITTER_BUFFER_MS / 1000.0));

    // Ring buffer capacity: 200ms worth — plenty of room, costs ~70 KB at 44.1k stereo
    const int capacity = static_cast<int> (sampleRate * 0.2);
    ringBuffer.resize (capacity, 2);
    bufferCapacityFrames.store (capacity);

    primed = false;
    underrunCount.store (0);

    // Start the network thread
    receiver.stop();
    receiver.start();
}

void ReaStreamReceiverProcessor::releaseResources()
{
    receiver.stop();
}

void ReaStreamReceiverProcessor::processBlock (juce::AudioBuffer<float>& buffer,
                                                juce::MidiBuffer&)
{
    const int numSamples  = buffer.getNumSamples();
    const int numChannels = buffer.getNumChannels();

    // Update stats for the editor
    const int avail = ringBuffer.getAvailable();
    bufferFillFrames.store (avail);

    // Wait until we have enough buffered to absorb jitter
    if (! primed)
    {
        if (avail < jitterBufferFrames)
        {
            buffer.clear();
            return;
        }
        primed = true;
    }

    // Underrun detection: if buffer has less than half a block, we'll get silence
    if (avail < numSamples)
    {
        underrunCount.fetch_add (1, std::memory_order_relaxed);
    }

    // Read from ring buffer into JUCE's per-channel pointers
    // LockFreeRingBuffer::readFrames expects float** with numChannels entries
    float* channelPtrs[2] = { nullptr, nullptr };
    for (int c = 0; c < (std::min) (numChannels, 2); ++c)
        channelPtrs[c] = buffer.getWritePointer (c);

    // If mono output but stereo ring buffer, use a temp for ch1 and discard
    float tempCh1[8192];
    if (numChannels < 2)
        channelPtrs[1] = tempCh1;

    ringBuffer.readFrames (channelPtrs, numSamples);

    // Zero any extra output channels beyond stereo
    for (int c = 2; c < numChannels; ++c)
        buffer.clear (c, 0, numSamples);
}

juce::AudioProcessorEditor* ReaStreamReceiverProcessor::createEditor()
{
    return new ReaStreamReceiverEditor (*this);
}

void ReaStreamReceiverProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    // Save port and identifier
    juce::XmlElement xml ("ReaStreamReceiverState");
    xml.setAttribute ("port", DEFAULT_PORT);
    xml.setAttribute ("identifier", juce::String ("default"));
    copyXmlToBinary (xml, destData);
}

void ReaStreamReceiverProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    auto xml = getXmlFromBinary (data, sizeInBytes);
    if (xml != nullptr && xml->hasTagName ("ReaStreamReceiverState"))
    {
        int port = xml->getIntAttribute ("port", DEFAULT_PORT);
        auto id  = xml->getStringAttribute ("identifier", "default");

        receiver.setPort (port);
        receiver.setIdentifier (id.toStdString());
    }
}

// --- Plugin instantiation ---
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ReaStreamReceiverProcessor();
}
