"""Explicit opt-in smoke test: opens and gracefully closes one isolated editor."""
import time
from app.tools.projects import open_project, close_project
from app.projects.lifecycle import project_lifecycle

if __name__ == '__main__':
    print(open_project('Streetlight'), flush=True)
    state = project_lifecycle.states.get('streetlight')
    if state:
        for _ in range(100):
            current = project_lifecycle.status('streetlight')
            if current.open:
                break
            time.sleep(0.1)
        print('IDENTITY', project_lifecycle.owned(state), 'OPEN', state.open, flush=True)
        result = close_project('Streetlight')
        print(result, flush=True)
        assert result['success'], result
