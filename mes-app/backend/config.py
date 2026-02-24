# backend/config.py
import os

class Config:
    SECRET_KEY = "secretvraimentsupersecret1234"
    
    # Configuration Base de Données
    MYSQL_HOST = "db"
    MYSQL_USER = "root"
    MYSQL_PASSWORD = "motdepasserootrobuste1234"
    
    # Noms des bases de données
    MYSQL_DB_MES = "mes4"
    MYSQL_DB_USERS = "users_db"