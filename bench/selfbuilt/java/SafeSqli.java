// EXPECT: clean | PreparedStatement 参数化
import java.sql.Connection;
import java.sql.PreparedStatement;

public class SafeSqli {
    public void q(Connection c, String id) throws Exception {
        PreparedStatement ps = c.prepareStatement("SELECT * FROM users WHERE id = ?");
        ps.setString(1, id);
        ps.executeQuery();
    }
}
