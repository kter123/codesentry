// EXPECT: vulnerable | CWE-78 Runtime.exec 拼接命令
public class VulnCmd {
    public void run(String input) throws Exception {
        Runtime.getRuntime().exec("sh -c " + input);
    }
}
