package io.pajio.privateinput;

import android.inputmethodservice.InputMethodService;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.inputmethod.InputConnection;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Dedicated, non-learning IME. No network permission, receivers, provider,
 * clipboard, files or content logging. ADB forwards this abstract Unix socket.
 * All input remains inside the currently authenticated execution host/device.
 */
public final class PrivateInputMethod extends InputMethodService {
    private static final String SOCKET = "pajio.privateinput.v1";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Object leaseLock = new Object();
    private volatile boolean closed;
    private volatile LocalServerSocket server;
    private volatile LocalSocket active;
    private byte[] lease;
    private long leaseDeadline;
    private int generation;

    @Override public void onCreate() {
        super.onCreate();
        Thread worker = new Thread(this::serve, "pajio-private-input");
        worker.setDaemon(true);
        worker.start();
    }
    @Override public boolean onEvaluateInputViewShown() { return false; }
    @Override public boolean onEvaluateFullscreenMode() { return false; }

    private void serve() {
        try {
            server = new LocalServerSocket(SOCKET);
            while (!closed) {
                try (LocalSocket socket = server.accept()) {
                    active = socket;
                    socket.setSoTimeout(2000);
                    int uid = socket.getPeerCredentials().getUid();
                    // Native apps cannot supply their own claimed UID. Kernel
                    // credentials restrict this endpoint to adbd/root or shell.
                    if (uid != 0 && uid != 2000) continue;
                    handle(socket);
                } catch (Exception ignored) {
                    // Never log an exception, packet or user-provided content.
                } finally { active = null; }
            }
        } catch (IOException ignored) {
            // Failed startup leaves no text path, rather than using broadcasts.
        } finally { closeServer(); }
    }

    private void handle(LocalSocket socket) throws Exception {
        DataInputStream input = new DataInputStream(socket.getInputStream());
        if (input.readInt() != 0x50494d31) return; // PIM1
        byte[] nonce = new byte[32];
        byte[] text = null;
        try {
            input.readFully(nonce);
            int operation = input.readUnsignedByte();
            int size = input.readInt();
            if ((operation != 1 && operation != 2) || size < 0 || size > 16384
                    || (operation == 2 && size != 0)) return;
            int epoch;
            synchronized (leaseLock) {
                long now = SystemClock.elapsedRealtime();
                if (lease != null && now > leaseDeadline) clearLease();
                if (lease == null) lease = nonce.clone();
                if (!Arrays.equals(lease, nonce)) { socket.getOutputStream().write(1); return; }
                leaseDeadline = now + 30000;
                epoch = generation;
                if (operation == 2) {
                    clearLease();
                    socket.getOutputStream().write(0);
                    return;
                }
            }
            text = new byte[size];
            input.readFully(text);
            if (size == 0) { socket.getOutputStream().write(3); return; }
            final byte[] buffer = text;
            final AtomicBoolean cancelled = new AtomicBoolean();
            final AtomicInteger result = new AtomicInteger(4);
            final CountDownLatch complete = new CountDownLatch(1);
            main.post(() -> {
                try {
                    synchronized (leaseLock) {
                        if (closed || cancelled.get() || epoch != generation
                                || SystemClock.elapsedRealtime() > leaseDeadline) return;
                        InputConnection connection = getCurrentInputConnection();
                        if (connection == null || !getCurrentInputStarted()) { result.set(2); return; }
                        // Decode only for the synchronous InputConnection call.
                        // Java/Android may copy immutable text; do not claim RAM
                        // zeroization beyond our owned mutable byte buffers.
                        CharSequence content = StandardCharsets.UTF_8.newDecoder()
                            .onMalformedInput(CodingErrorAction.REPORT)
                            .onUnmappableCharacter(CodingErrorAction.REPORT)
                            .decode(ByteBuffer.wrap(buffer));
                        result.set(connection.commitText(content, 1) ? 0 : 4);
                    }
                } catch (Exception ignored) { result.set(3); }
                finally { Arrays.fill(buffer, (byte) 0); complete.countDown(); }
            });
            text = null; // The main-thread callback now owns and clears buffer.
            if (!complete.await(1500, TimeUnit.MILLISECONDS)) cancelled.set(true);
            socket.getOutputStream().write(result.get());
        } finally {
            Arrays.fill(nonce, (byte) 0);
            if (text != null) Arrays.fill(text, (byte) 0);
        }
    }

    private void clearLease() {
        if (lease != null) Arrays.fill(lease, (byte) 0);
        lease = null;
        generation++;
    }
    private void closeServer() {
        try { if (active != null) active.close(); } catch (IOException ignored) {}
        try { if (server != null) server.close(); } catch (IOException ignored) {}
    }
    @Override public void onDestroy() {
        closed = true;
        synchronized (leaseLock) { clearLease(); }
        closeServer();
        super.onDestroy();
    }
}
