#pragma once
#include "LockFreeRingBuffer.h"
#include "ReaStreamParser.h"

#ifdef _WIN32
  #include <WinSock2.h>
  #include <WS2tcpip.h>
  using SocketType = SOCKET;
  static constexpr SocketType InvalidSocket = INVALID_SOCKET;
#else
  #include <sys/socket.h>
  #include <netinet/in.h>
  #include <unistd.h>
  #include <fcntl.h>
  using SocketType = int;
  static constexpr SocketType InvalidSocket = -1;
#endif

#include <atomic>
#include <thread>
#include <cstring>
#include <string>

/**
 * Dedicated UDP receiver thread.
 *
 * Runs a tight recvfrom() loop on a high-priority thread, parses ReaStream
 * packets, and pushes audio into the lock-free ring buffer.  The audio thread
 * never touches the socket.
 */
class UdpReceiver
{
public:
    UdpReceiver (LockFreeRingBuffer& ringBuffer)
        : ring (ringBuffer)
    {
    }

    ~UdpReceiver()
    {
        stop();
    }

    void setPort (int port)           { listenPort = port; }
    void setIdentifier (const std::string& id) { identifier = id; }

    bool start()
    {
        if (running.load())
            return true;

#ifdef _WIN32
        WSADATA wsa;
        WSAStartup (MAKEWORD (2, 2), &wsa);
#endif

        sock = socket (AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (sock == InvalidSocket)
            return false;

        // Allow address reuse
        int yes = 1;
        setsockopt (sock, SOL_SOCKET, SO_REUSEADDR,
                    reinterpret_cast<const char*> (&yes), sizeof (yes));

        // Increase receive buffer to 2 MB to absorb bursts
        int rcvBuf = 2 * 1024 * 1024;
        setsockopt (sock, SOL_SOCKET, SO_RCVBUF,
                    reinterpret_cast<const char*> (&rcvBuf), sizeof (rcvBuf));

        sockaddr_in addr {};
        addr.sin_family      = AF_INET;
        addr.sin_port        = htons (static_cast<uint16_t> (listenPort));
        addr.sin_addr.s_addr = INADDR_ANY;

        if (bind (sock, reinterpret_cast<sockaddr*> (&addr), sizeof (addr)) != 0)
        {
            closeSocket();
            return false;
        }

        // Set socket timeout so recvfrom wakes up periodically to check `running`
#ifdef _WIN32
        DWORD timeout = 100; // ms
        setsockopt (sock, SOL_SOCKET, SO_RCVTIMEO,
                    reinterpret_cast<const char*> (&timeout), sizeof (timeout));
#else
        timeval tv { 0, 100000 }; // 100ms
        setsockopt (sock, SOL_SOCKET, SO_RCVTIMEO,
                    reinterpret_cast<const char*> (&tv), sizeof (tv));
#endif

        running.store (true);
        receiverThread = std::thread ([this] { receiveLoop(); });

        // Boost thread priority
#ifdef _WIN32
        SetThreadPriority (receiverThread.native_handle(), THREAD_PRIORITY_HIGHEST);
#endif

        return true;
    }

    void stop()
    {
        running.store (false);

        if (receiverThread.joinable())
            receiverThread.join();

        closeSocket();

#ifdef _WIN32
        WSACleanup();
#endif
    }

    // Stats (read from any thread)
    std::atomic<uint64_t> packetsReceived { 0 };
    std::atomic<uint64_t> packetsDropped  { 0 };
    std::atomic<int>      lastSampleRate  { 0 };
    std::atomic<int>      lastChannels    { 0 };

private:
    void receiveLoop()
    {
        uint8_t buf[ReaStream::MAX_PACKET];

        while (running.load (std::memory_order_relaxed))
        {
            sockaddr_in sender {};
            int senderLen = sizeof (sender);

#ifdef _WIN32
            int n = recvfrom (sock, reinterpret_cast<char*> (buf), sizeof (buf), 0,
                              reinterpret_cast<sockaddr*> (&sender), &senderLen);
#else
            auto n = recvfrom (sock, buf, sizeof (buf), 0,
                               reinterpret_cast<sockaddr*> (&sender),
                               reinterpret_cast<socklen_t*> (&senderLen));
#endif
            if (n <= 0)
                continue; // timeout or error — just retry

            auto pkt = ReaStream::parse (buf, static_cast<int> (n));

            if (! pkt.valid)
            {
                packetsDropped.fetch_add (1, std::memory_order_relaxed);
                continue;
            }

            // Filter by identifier if set
            if (! identifier.empty())
            {
                if (std::strncmp (pkt.identifier, identifier.c_str(),
                                  ReaStream::IDENT_LEN) != 0)
                    continue;
            }

            lastSampleRate.store (pkt.sampleRate, std::memory_order_relaxed);
            lastChannels.store (pkt.channels, std::memory_order_relaxed);

            // Push non-interleaved audio into ring buffer
            ring.writeNonInterleaved (pkt.audioData, pkt.numFrames, pkt.channels);

            packetsReceived.fetch_add (1, std::memory_order_relaxed);
        }
    }

    void closeSocket()
    {
        if (sock != InvalidSocket)
        {
#ifdef _WIN32
            closesocket (sock);
#else
            close (sock);
#endif
            sock = InvalidSocket;
        }
    }

    LockFreeRingBuffer& ring;
    SocketType sock = InvalidSocket;
    std::thread receiverThread;
    std::atomic<bool> running { false };

    int listenPort = 58710;
    std::string identifier = "default";
};
