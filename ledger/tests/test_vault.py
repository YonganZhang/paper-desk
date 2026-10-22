import unittest
import test_tracking
import db
import credential_vault as vault

class VaultTests(unittest.TestCase):
    def test_permissions_encryption_redaction_and_upsert(self):
        client=test_tracking.PortalTests.client
        rw=test_tracking.PortalTests.rw
        ro=test_tracking.PortalTests.ro
        path='/api/v1/journal-accounts/TestJournal'
        b={'url':'https://example.org','account':'test@example.org','password':'synthetic-private-password-389'}
        c=db.connect()
        before=c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0]
        self.assertEqual(client.put(path,json=b,headers=ro).status_code,403)
        self.assertEqual(client.put(path,json=b,headers=rw).status_code,200)
        self.assertEqual(client.put(path,json=b,headers=rw).status_code,200)
        self.assertEqual(client.get(path,headers=ro).status_code,403)
        masked=client.get(path,headers=rw)
        self.assertNotIn(b['password'],masked.text)
        self.assertNotIn(b['account'],masked.text)
        revealed=client.get(path+'?reveal=true',headers=rw)
        self.assertEqual(revealed.json()['password'],b['password'])
        self.assertEqual(revealed.headers['cache-control'],'no-store')
        payload=c.execute('SELECT payload FROM private_journal_accounts').fetchone()[0]
        self.assertNotIn(b['password'],payload)
        self.assertNotIn(b['account'],payload)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM submissions').fetchone()[0],before)
        logs=' '.join(r[0] for r in c.execute('SELECT detail FROM audit'))
        self.assertNotIn(b['password'],logs)
        code=test_tracking.PortalTests().new()
        client.patch('/api/v1/papers/'+code,json={'notes':b['password']},headers=rw)
        self.assertNotIn(b['password'],client.get('/api/v1/papers/'+code,headers=ro).text)
        response=client.get('/private-accounts',follow_redirects=False)
        self.assertNotEqual(response.status_code,200)
        vault.initialize(c)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM private_journal_accounts').fetchone()[0],1)
        c.close()

    @classmethod
    def setUpClass(cls):
        test_tracking.PortalTests.setUpClass()

if __name__=='__main__':unittest.main()
