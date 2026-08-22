export type ParsedArguments = {
  command: string | undefined;
  positional: string[];
  flags: Record<string, string>;
};

export function parseArguments(arguments_: string[]): ParsedArguments {
  const [command, ...tokens] = arguments_;
  const positional: string[] = [];
  const flags: Record<string, string> = {};
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]!;
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }
    const name = token.slice(2);
    const value = tokens[index + 1];
    if (!value || value.startsWith("--"))
      throw new Error(`missing value for --${name}`);
    flags[name] = value;
    index += 1;
  }
  return { command, positional, flags };
}

export function requiredFlag(
  flags: Record<string, string>,
  name: string,
): string {
  const value = flags[name];
  if (!value) throw new Error(`--${name} is required`);
  return value;
}
