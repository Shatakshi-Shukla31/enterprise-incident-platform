import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button, Card, ErrorNote, Field, Loading, Pagination, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { humanize } from "../lib/format";
import type { Page, Role, Team, User } from "../lib/types";

const ROLES: Role[] = ["requester", "agent", "manager", "admin"];
const EMPTY = { email: "", full_name: "", password: "", role: "requester" as Role, team_id: "" };

export function UsersPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [form, setForm] = useState(EMPTY);
  const users = useQuery({
    queryKey: ["users", page],
    queryFn: () => api.get<Page<User>>(`/users?page=${page}&page_size=20`),
    placeholderData: keepPreviousData,
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: () => api.post("/users", { ...form, team_id: form.team_id ? Number(form.team_id) : null }),
    onSuccess: () => {
      setForm(EMPTY);
      refresh();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: Role; is_active?: boolean; team_id?: number | null }) =>
      api.patch(`/users/${id}`, body),
    onSuccess: refresh,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-ink">Users</h1>
      <Card title="Add a user">
        <form onSubmit={submit} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Field label="Name">
              <input className={inputClass} required minLength={2} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </Field>
            <Field label="Email">
              <input className={inputClass} type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </Field>
            <Field label="Password">
              <input className={inputClass} type="password" autoComplete="new-password" required minLength={12} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </Field>
            <Field label="Role">
              <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {humanize(role)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Team">
              <select className={inputClass} value={form.team_id} onChange={(e) => setForm({ ...form, team_id: e.target.value })}>
                <option value="">None</option>
                {teams.data?.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <ErrorNote error={create.error} />
          <Button type="submit" variant="secondary" disabled={create.isPending}>
            Create user
          </Button>
        </form>
      </Card>

      <ErrorNote error={users.error ?? update.error} />
      {users.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-ink-3">
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Email</th>
                  <th className="px-3 py-2 font-medium">Role</th>
                  <th className="px-3 py-2 font-medium">Team</th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.data?.items.map((person) => (
                  <tr key={person.id} className="border-b border-line last:border-0">
                    <td className="px-3 py-2 text-ink">{person.full_name}</td>
                    <td className="px-3 py-2 text-ink-2">{person.email}</td>
                    <td className="px-3 py-2">
                      <select
                        aria-label={`Role for ${person.full_name}`}
                        className="rounded-md border border-line bg-surface px-2 py-1 text-sm"
                        value={person.role}
                        onChange={(e) => update.mutate({ id: person.id, role: e.target.value as Role })}
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {humanize(role)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2 text-ink-2">{teams.data?.find((team) => team.id === person.team_id)?.name ?? "—"}</td>
                    <td className="px-3 py-2 text-right">
                      <Button variant="ghost" onClick={() => update.mutate({ id: person.id, is_active: false })}>
                        Deactivate
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {users.data && <Pagination page={users.data.page} pageSize={users.data.page_size} total={users.data.total} onChange={setPage} />}
        </>
      )}
    </div>
  );
}
