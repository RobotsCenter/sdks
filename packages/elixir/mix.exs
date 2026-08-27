defmodule RobotsCenter.MixProject do
  use Mix.Project

  def project do
    [
      app: :robots_center,
      version: "0.1.0",
      elixir: "~> 1.18",
      start_permanent: Mix.env() == :prod,
      description: "Official Elixir SDK for the Robots Center API",
      package: package(),
      deps: deps(),
      docs: [main: "readme", extras: ["README.md"]]
    ]
  end

  def application do
    [extra_applications: [:logger, :ssl]]
  end

  defp deps do
    [
      {:req, "~> 0.5"},
      {:phoenix_client, "~> 0.11"},
      {:ex_doc, "~> 0.34", only: :dev, runtime: false}
    ]
  end

  defp package do
    [
      licenses: ["Apache-2.0"],
      links: %{
        "Documentation" => "https://robotscenter.net/docs",
        "GitHub" => "https://github.com/RobotsCenter/sdks"
      },
      files: ~w(lib mix.exs README.md LICENSE NOTICE)
    ]
  end
end
