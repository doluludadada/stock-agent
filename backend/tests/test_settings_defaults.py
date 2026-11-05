"""A settings field that keeps a code default beside its config/appsetting.yaml value never disagrees with the YAML."""

import settings_defaults
from support.settings import APPSETTING

from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import load_yaml


def test_no_code_default_disagrees_with_the_shipped_settings() -> None:
    duplicated = settings_defaults.duplicated_settings(AppConfig, load_yaml(APPSETTING))

    assert [str(setting) for setting in duplicated if setting.differs] == []
