api:       cd backend && DJANGO_SETTINGS_MODULE=bikeshare.settings.local .venv/bin/python3 manage.py runserver
listener:  cd backend && DJANGO_SETTINGS_MODULE=bikeshare.settings.local .venv/bin/python3 manage.py mqtt_listener
sweep:     cd backend && DJANGO_SETTINGS_MODULE=bikeshare.settings.local .venv/bin/python3 manage.py sweep_timeouts
heartbeat: cd backend && DJANGO_SETTINGS_MODULE=bikeshare.settings.local .venv/bin/python3 manage.py station_heartbeat
sim:       cd simulator && .venv/bin/python3 -m station_sim.main
