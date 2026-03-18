#pragma once
#include <cstdint>
#include <cstring>

/**
 * ReaStream UDP protocol parser.
 *
 * Wire format (little-endian):
 *   Offset  Type        Field
 *   0       char[4]     Magic "MRSR"
 *   4       uint32      Packet size (header + audio bytes)
 *   8       char[32]    Identifier (null-padded ASCII)
 *   40      uint8       Channels
 *   41      uint32      Sample rate
 *   45      uint16      Audio byte count
 *   47      float32[]   Audio data (non-interleaved: ch0 then ch1)
 */
namespace ReaStream
{

static constexpr int HEADER_SIZE = 47;
static constexpr int MAX_PACKET  = 2048;
static constexpr int IDENT_LEN   = 32;

#pragma pack(push, 1)
struct Header
{
    char     magic[4];       // "MRSR"
    uint32_t packetSize;
    char     identifier[32]; // null-padded
    uint8_t  channels;
    uint32_t sampleRate;
    uint16_t audioBytes;
};
#pragma pack(pop)

static_assert (sizeof (Header) == 47, "ReaStream header must be 47 bytes");

struct ParsedPacket
{
    bool     valid         = false;
    int      channels      = 0;
    int      sampleRate    = 0;
    int      numFrames     = 0;
    char     identifier[IDENT_LEN + 1] = {};
    const float* audioData = nullptr; // points into the raw packet buffer
};

/** Parse a ReaStream UDP packet in-place. audioData points into `data`. */
inline ParsedPacket parse (const uint8_t* data, int dataSize)
{
    ParsedPacket result;

    if (dataSize < HEADER_SIZE)
        return result;

    const auto* hdr = reinterpret_cast<const Header*> (data);

    if (std::memcmp (hdr->magic, "MRSR", 4) != 0)
        return result;

    if (hdr->channels == 0 || hdr->sampleRate == 0)
        return result;

    const int audioBytes = hdr->audioBytes;
    const int expectedSize = HEADER_SIZE + audioBytes;

    if (dataSize < expectedSize)
        return result;

    const int frameSizeBytes = hdr->channels * static_cast<int> (sizeof (float));
    if (frameSizeBytes == 0 || audioBytes % frameSizeBytes != 0)
        return result;

    result.valid      = true;
    result.channels   = hdr->channels;
    result.sampleRate = hdr->sampleRate;
    result.numFrames  = audioBytes / frameSizeBytes;
    result.audioData  = reinterpret_cast<const float*> (data + HEADER_SIZE);

    std::memcpy (result.identifier, hdr->identifier, IDENT_LEN);
    result.identifier[IDENT_LEN] = '\0';

    return result;
}

} // namespace ReaStream
