# DeltaSherlock Django Server
A Django implementation of the fingerprint analyzation API

## A Note on Repo Organization
This repository contains the DeltaSherlock **[Django](https://www.djangoproject.com) server**. If you're looking for the **utility package**, head over to [utility-package](https://github.com/deltasherlock/utility-package/) This repo is structured in [typical Django project fashion](https://docs.djangoproject.com/en/1.10/intro/tutorial01/#creating-a-project), with `deltasherlock_server` serving as the "app" directory and `django-server` serving as the "project" directory.

## Installation
1. Follow the installation instructions for the utility-package if you haven't already
2. Install the Redis (queuing server) `sudo apt install redis-server`
3. Install Django + dependencies `sudo pip3 install --upgrade django djangorestframework django-simple-history markdown redis rq pytz `
4. Clone this repo somewhere easy, like to your home directory: git clone https://github.com/deltasherlock/django-server.git
5. `cd` into the repo, prepare the databases, create an admin account, and launch the web server
```bash
cd django-server
python3 manage.py makemigrations
python3 manage.py migrate
python3 manage.py createsuperuser
python3 manage.py runserver 0.0.0.0:8000
```
Then pop open a web browser, navigate over to `http://<your_server_ip>:8000/admin`, and have fun!

## Troubleshooting
* Triple check to make sure all of the dependencies were installed correctly, for both this repo and the utility package
* Check your firewall and VM "security policy" to ensure it allows inbound connections through port 8000
