import postgres from 'postgres'
import { localDay } from '../functions/_shared/core.ts'

export const testToken = '123456:playwright-test'
export const testUrl = Deno.env.get('ATTENDANCE_TEST_DATABASE_URL') ?? 'postgresql://attendance_test@127.0.0.1:15439/attendance_test'

export async function fixtures(): Promise<void> {
  const url = new URL(testUrl)
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.pathname !== '/attendance_test') {
    throw new Error('Fixture initialization requires the isolated loopback attendance_test database.')
  }
  const sql = postgres(testUrl, { max: 1, prepare: false, onnotice: () => {} })
  try {
    await sql.unsafe(`DO $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='postgres') THEN CREATE ROLE postgres NOLOGIN; END IF;
    END $$; DROP SCHEMA public CASCADE; CREATE SCHEMA public;`)
    const filenames: string[] = []
    for await (const file of Deno.readDir(new URL('../migrations/', import.meta.url))) if (file.name.endsWith('.sql')) filenames.push(file.name)
    for (const filename of filenames.sort()) {
      await sql.unsafe(await Deno.readTextFile(new URL('../migrations/' + filename, import.meta.url)))
    }
    await sql.unsafe(`INSERT INTO users(id,telegram_id,username,full_name,started_at) VALUES
      (101,101,'owner','Алина Мирова',timezone('UTC',now())),(102,102,'manager','Андрей Орлов',timezone('UTC',now())),
      (103,103,'recipient','Ирина Соколова',timezone('UTC',now())),(104,9876543210,'parent_without_class','Родитель без класса',timezone('UTC',now()));
      SELECT setval('users_id_seq',104,true);
      INSERT INTO classes(id,name,name_key,is_active) VALUES(1,'10-В','10-в',true),(2,'9-А','9-а',true);
      SELECT setval('classes_id_seq',2,true);
      INSERT INTO report_schedules(class_id,timezone) VALUES(1,'Asia/Tashkent'),(2,'Asia/Tashkent');
      INSERT INTO manager_assignments(user_id,class_id) VALUES(102,1);
      INSERT INTO report_recipients(user_id,class_id) VALUES(103,1);
      INSERT INTO user_roles(user_id,role) VALUES(102,'MANAGER'),(103,'REPORT_RECIPIENT');`)
    const names = ['Авдеев Александр', 'Белова Инна', 'Власов Игорь', 'Громова Елена'], today = localDay()
    for (let index = 0; index < names.length; index++) {
      const [pupil] = await sql`INSERT INTO students(full_name,class_id,active_name_key) VALUES(${names[index]},1,${names[index].toLocaleLowerCase('ru')}) RETURNING id`
      await sql`INSERT INTO enrollments(student_id,class_id,starts_on) VALUES(${pupil.id},1,${today})`
      if (index < 3) await sql`INSERT INTO attendance(student_id,date,status,marked_by) VALUES(${pupil.id},${today},${index < 2 ? 1 : 2},101)`
    }
  } finally { await sql.end() }
}

export const testConfiguration = { token: testToken, ownerId: 101, miniAppUrl: 'http://127.0.0.1:8109',
  webhookSecret: 'synthetic-webhook-secret', schedulerSecret: 'synthetic-scheduler-secret', url: testUrl,
  projectUrl: 'http://127.0.0.1:8109', test: true }
