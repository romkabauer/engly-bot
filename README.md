# Engly - Telegram Bot

Telegram Bot for English-interview preparing

Done:
- random questions
- pick from list questions
- voice recognition (using Google SR API)
- check gramma (using free LanguageTool API)

Doing:
- STORY: complete interview with saving progress
- BUG: if there is no "replacements" in gramma check API answer - bot reply fails

To Do:
- STORY: Deploy as a container
- STORY: Deploy on a host, not locally
- STORY: implement db (or use Telegram instruments) to not lose all users progress after redeploy - db also as a container? k8s?
- TECH DEBT: refactor SR and Grammar Check modules to let use them as a lib
- STORY: course option (info with tips and examples in the form of a daily practice)
