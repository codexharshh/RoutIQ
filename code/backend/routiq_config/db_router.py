class DatabaseRouter:
    """Keep RoutIQ core data and legacy road-segment data in separate SQLite files.

    Default Django user accounts, pothole records, and road observations use
    ``routiq.sqlite3`` (the default database). Only models from the ``government``
    app use ``routiq_government.sqlite3``. Cross-database ORM relations are
    deliberately denied because SQLite cannot enforce foreign keys across files.
    """

    route_app_labels = {"government"}

    def db_for_read(self, model, **hints):
        return "government" if model._meta.app_label in self.route_app_labels else "default"

    def db_for_write(self, model, **hints):
        return "government" if model._meta.app_label in self.route_app_labels else "default"

    def allow_relation(self, obj1, obj2, **hints):
        db1 = obj1._state.db
        db2 = obj2._state.db
        if not db1 or not db2:
            return None
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == "government"
        if db == "government":
            return False
        return db == "default"
