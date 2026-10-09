package io.pajio.privateinput;

import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import java.io.DataInputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;

/** Executed by trusted adbd with binary stdin. Verify the server's kernel UID
 * before transmitting any content, so another app cannot squat the socket.
 * Not an exported Android component. Command arguments contain only the UID.
 */
public final class SocketClient {
    public static void main(String[] args) {
        byte[] header = new byte[41];
        byte[] payload = null;
        int result = 5;
        try (LocalSocket socket = new LocalSocket()) {
            if (args.length != 1) return;
            int expectedUid = Integer.parseInt(args[0]);
            if (expectedUid < 10000) return;
            socket.connect(new LocalSocketAddress("pajio.privateinput.v1", LocalSocketAddress.Namespace.ABSTRACT));
            socket.setSoTimeout(2000);
            if (socket.getPeerCredentials().getUid() != expectedUid) return;
            DataInputStream input = new DataInputStream(System.in);
            input.readFully(header);
            int size = ByteBuffer.wrap(header, 37, 4).getInt();
            if (size < 0 || size > 16384) return;
            payload = new byte[size];
            input.readFully(payload);
            socket.getOutputStream().write(header);
            socket.getOutputStream().write(payload);
            result = socket.getInputStream().read();
        } catch (Exception ignored) {
            // No stderr/stack trace: native callers get only an opaque status.
        } finally {
            Arrays.fill(header, (byte) 0);
            if (payload != null) Arrays.fill(payload, (byte) 0);
            try { System.out.write(result < 0 ? 5 : result); System.out.flush(); }
            catch (Exception ignored) {}
            System.exit(0); // app_process otherwise keeps its Binder pool alive.
        }
    }
}
