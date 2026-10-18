import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;

public class FileService {
    // CVE 模式：CWE-22 Path Traversal——用户输入拼进路径直接读文件
    public String readReport(String name) throws Exception {
        String path = "/var/data/reports/" + name;
        File f = new File(path); // sink：line 9
        return Files.readString(Paths.get(f.toURI()));
    }
}
