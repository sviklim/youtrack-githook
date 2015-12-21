import re
import dateutil.parser
from flask import Flask, request, Response
from youtrack.connection import Connection
from youtrack import YouTrackException

# Configuration
YOUTRACK_URL = ''
YOUTRACK_USERNAME = ''
YOUTRACK_PASSWORD = ''
YOUTRACK_APIKEY = ''
STASH_HOST= ''
REGEX = '([A-Z]+-\d+)'
DEFAULT_USER = ''

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_pyfile('settings.cfg', silent=True)
app.config.from_envvar('GITHOOK_SETTINGS', silent=True)


# Application
@app.route('/')
def ping():
    return 'ping'

@app.route('/hook', methods=['POST'])
@app.route('/push_event', methods=['POST'])
def push_event_hook():
    push_event = request.json
    app.logger.debug(push_event)
    repo_name = push_event['repository']['name']
    repo_project = push_event['repository']['project']['key']
    repo_slug = push_event['repository']['slug']
    repo_homepage = [STASH_HOST, "projects", repo_project, "repos", repo_slug].join("/")
    refspec = push_event['refChanges'][0]['refId'].replace("refs/heads/", "")
    
    app.logger.debug('Received push event in branch %s on repository %s', refspec, repo_name)

    for commit in push_event['changesets']['values']:
        commit = commit['toCommit']
        commit_url = [repo_homepage, "commits", commit['id']].join("/") 
        app.logger.debug(
            'Processing commit %s by %s (%s) in %s',
            commit['id'],
            commit['author']['name'],
            commit['author']['email'],
            commit_url,
        )
        commit_time = dateutil.parser.parse(commit['authorTimestamp'])
        issues = re.findall(app.config['REGEX'], commit['message'], re.MULTILINE)
        if not issues:
            app.logger.debug('''Didn't find any referenced issues in commit %s''', commit['id'])
        else:
            app.logger.debug('Found %d referenced issues in commit %s', len(issues), commit['id'])
            yt = Connection(app.config['YOUTRACK_URL'], app.config['YOUTRACK_USERNAME'], app.config['YOUTRACK_PASSWORD'])

            user_login = get_user_login(yt, commit['author']['emailAddress'])
            if user_login is None:
                app.logger.warn("Couldn't find user with email address %s. Using default user.", commit['author']['emailAddress'])
                default_user = yt.getUser(app.config['DEFAULT_USER'])
                user_login = default_user['login']

            for issue_id in issues:
                app.logger.debug('Processing reference to issue %s', issue_id)
                try:
                    yt.getIssue(issue_id)
                    comment_string = (
                        'Commit [%(url)s %(id)s] on branch %(refspec)s in [%(repo_homepage)s %(repo_name)s] made by %(author)s on %(date)s\n{quote}%(message)s{quote}' %  {
                            'url': commit_url,
                            'id': commit['id'],
                            'author': commit['author']['name'],
                            'date': str(commit_time),
                            'message': commit['message'],
                            'repo_homepage': repo_homepage,
                            'repo_name': repo_name,
                            'refspec': refspec
                        })
                    app.logger.debug(comment_string)
                    yt.executeCommand(issueId=issue_id, command='comment', comment=comment_string.encode('utf-8'),
                                      run_as=user_login.encode('utf-8'))
                except YouTrackException:
                    app.logger.warn("Couldn't find issue %s", issue_id)
    return Response('Push event processed. Thanks!', mimetype='text/plain')


def get_user_login(yt, email):
    """Given a youtrack connection and an email address, try to find the login
    name for a user. Returns `None` if no (unique) user was found.
    """
    users = yt.getUsers({'q': email})
    if len(users) == 1:
        return users[0]['login']
    else:
        # Unfortunately, youtrack does not seem to have an exact search
        for user in users:
            try:
                full_user = yt.getUser(user['login'])
            except YouTrackException:
                pass
            else:
                if full_user['email'] == email:
                    return full_user['login']
    return None


if __name__ == '__main__':
    app.run()
