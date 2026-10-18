// EXPECT: clean | 固定命令数组
public class SafeCmd {
    public void run(String[] fixedArgs) throws Exception {
        Runtime.getRuntime().exec(fixedArgs);
    }
}
