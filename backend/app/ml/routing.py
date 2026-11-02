import numpy as np


class RuleRouter:
    """Baseline: the team that historically handled most tickets of the predicted category."""

    def __init__(self, classifier, category_teams: dict[str, dict[str, float]], teams: list[str]):
        self.classifier = classifier
        self.category_teams = category_teams
        self.classes_ = np.array(sorted(teams))

    def predict_proba(self, texts) -> np.ndarray:
        category_probabilities = self.classifier.predict_proba(texts)
        team_index = {team: position for position, team in enumerate(self.classes_)}
        output = np.zeros((len(texts), len(self.classes_)))
        for column, category in enumerate(self.classifier.classes_):
            for team, share in self.category_teams.get(str(category), {}).items():
                output[:, team_index[team]] += category_probabilities[:, column] * share
        return output
