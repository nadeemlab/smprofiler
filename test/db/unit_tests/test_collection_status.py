"""Test the promotion/demotion functions for public/private collections."""

from smprofiler.db.publish_promote import PublisherPromoter


def test_collection_management():
    collection = 'abc-123'
    database_config_file='.smprofiler_db.config.container'
    promoter = PublisherPromoter(database_config_file)
    promoter.promote(collection)
    promoter.demote(collection)


if __name__=='__main__':
    test_collection_management()
