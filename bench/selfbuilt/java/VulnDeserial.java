// EXPECT: vulnerable | CWE-502 直接 readObject
import java.io.ObjectInputStream;

public class VulnDeserial {
    public Object read(ObjectInputStream ois) throws Exception {
        return ois.readObject();
    }
}
