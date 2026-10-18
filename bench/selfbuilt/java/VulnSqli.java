// EXPECT: vulnerable | CWE-89 SQL 注入：字符串拼接进 Statement.executeQuery
import java.sql.Statement;

public class VulnSqli {
    public void q(Statement s, String id) throws Exception {
        s.executeQuery("SELECT * FROM users WHERE id = " + id);
    }
}
