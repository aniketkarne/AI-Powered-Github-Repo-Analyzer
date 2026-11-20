import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import axios from "axios";
import App from "./App";

jest.mock("axios");
// chart.js cannot acquire a canvas context under jsdom and throws from its
// effect, which unmounts the whole tree. The charts are not under test here.
jest.mock("react-chartjs-2", () => ({
  Bar: () => null,
  Pie: () => null,
}));

const profileFixture = {
  profile: {
    login: "octo",
    name: "Octo Cat",
    avatar_url: "https://example.test/avatar.png",
    bio: "builds things",
    followers: 10,
    following: 5,
    public_repos: 1,
    html_url: "https://example.test/octo",
  },
  repos: [
    {
      name: "repo-one",
      description: "first repo",
      stars: 4,
      forks: 5,
      language: "Python",
      pushed_at: "2026-01-01T00:00:00Z",
    },
  ],
  language_breakdown: [{ language: "Python", count: 1, percent: 100 }],
  star_trend: [{ repo: "repo-one", stars: 4 }],
  fork_trend: [{ repo: "repo-one", forks: 5 }],
  heatmap: ["2026-01-01T00:00:00Z"],
};

const reportFixture = {
  reports: [
    {
      repo: "repo-one",
      analysis: {
        summary: "A fine repo.",
        suggestions: ["Add a LICENSE section"],
        readability_score: 8.25,
        missing_sections: ["License", "Contributing"],
      },
    },
  ],
};

beforeEach(() => {
  axios.get.mockReset();
});

function typeUsername(value) {
  fireEvent.change(screen.getByPlaceholderText("GitHub username..."), {
    target: { value },
  });
}

test("renders the analyzer title", () => {
  render(<App />);
  expect(screen.getByText("GitHub Repo Analyzer")).toBeTruthy();
});

test("encodes the username in the profile request URL", async () => {
  axios.get.mockResolvedValue({ data: profileFixture });
  render(<App />);
  typeUsername("octo/cat 1");
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() =>
    expect(axios.get).toHaveBeenCalledWith(
      "http://localhost:8000/api/profile/octo%2Fcat%201"
    )
  );
});

test("does not fire duplicate requests while a request is in flight", async () => {
  let resolveRequest;
  axios.get.mockImplementation(
    () => new Promise((resolve) => (resolveRequest = resolve))
  );
  render(<App />);
  typeUsername("octo");
  const input = screen.getByPlaceholderText("GitHub username...");
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(axios.get).toHaveBeenCalledTimes(1);
  resolveRequest({ data: profileFixture });
  await waitFor(() => expect(screen.getByText("Octo Cat")).toBeTruthy());
});

test("clears stale profile data when a new request fails", async () => {
  axios.get.mockResolvedValueOnce({ data: profileFixture });
  render(<App />);
  typeUsername("octo");
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(screen.getByText("repo-one")).toBeTruthy());

  axios.get.mockRejectedValueOnce(
    Object.assign(new Error("boom"), {
      response: { data: { detail: "User not found" } },
    })
  );
  typeUsername("ghost");
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(screen.getByText("User not found")).toBeTruthy());
  expect(screen.queryByText("repo-one")).toBeNull();
  expect(screen.queryByText("Octo Cat")).toBeNull();
});

test("renders the README quality report from the readme-report endpoint", async () => {
  axios.get.mockResolvedValue({ data: reportFixture });
  render(<App />);
  typeUsername("octo");
  fireEvent.click(screen.getByRole("button", { name: "README Report" }));
  await waitFor(() =>
    expect(axios.get).toHaveBeenCalledWith(
      "http://localhost:8000/api/profile/octo/readme-report"
    )
  );
  expect(await screen.findByText("A fine repo.")).toBeTruthy();
  expect(screen.getByText("Add a LICENSE section")).toBeTruthy();
  expect(screen.getByText("Missing sections: License, Contributing")).toBeTruthy();
  expect(screen.getByText(/Flesch–Kincaid grade 8\.3/)).toBeTruthy();
});

test("shows an empty state when no READMEs were analyzed", async () => {
  axios.get.mockResolvedValue({ data: { reports: [] } });
  render(<App />);
  typeUsername("octo");
  fireEvent.click(screen.getByRole("button", { name: "README Report" }));
  expect(
    await screen.findByText("No READMEs found to analyze.")
  ).toBeTruthy();
});
